#!/usr/bin/env python3
"""Bounded dependency-reachability workload for Sigma-Glyph 0.8.0 (Book I, C1 -> SKI).

DRAFT for s0fractal/sigma-glyph#68. Every vector in this file is SYNTHETIC: the
graph contract and the real wheel fixtures are frozen in s0fractal/warrant#150, and
`canonical()` below is a placeholder for that contract, not the contract itself.

    input = P C R T                   (four closed terms; P is the same for every graph)
    C     = columns of the reflexive adjacency matrix, DESCENDING column order
            C[j][i] = TRUE iff i == j or edge i -> j
    R, T  = root and target indicator vectors (ascending node order)
    P C R T  ->  K (TRUE: some target is reachable from some root)
             |   K I (FALSE: none is)

Sigma performs the search: P runs n-1 rounds of r'[j] = OR_i (r[i] AND C[j][i]).
The host computes no verdict; `reference()` is an independent traversal used only
to check Sigma's answer.

    python3 reach.py selftest          # synthetic controls (book1 oracle)
    python3 reach.py measure [NMAX]    # ATP / wall-time scaling (synthetic)
    python3 reach.py provider          # PAUSED -> checked resume through sigma_provider
"""
import hashlib
import json
import re
import sys
import time

import sigma_glyph as G  # the installed provider's kernel (sigma-glyph 0.8.0)

ENCODER_ID = "warrant-dep-reach/draft-1"
TRUE_T, FALSE_T = ("lit", G.sha(b"K")), ("app", ("lit", G.sha(b"K")), ("lit", G.sha(b"I")))
VERDICT = {G.K_H: True, G.FALSE_H: False}           # canonical result terms
N_MAX = 7                                             # admission (see DESIGN.md §4)
ATP_ADMIT = 10_000_000                                # = sigma_glyph.VERIFIER_LIMITS max_atp


class Refused(Exception):
    """The input is outside the contract. Never a FALSE verdict."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# ----------------------------------------------------------------- lambda frontend
# A tiny closed-term DSL: `\x y. body`, juxtaposition, parentheses, names of earlier
# definitions (inlined as closed subterms) and the SKI atoms. C1 is sigma_glyph.c1.
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


# Encoding rules (DESIGN.md §2). Each one fixes a measured blow-up of lazy C1 code:
#  R1 lambda-lifted: no definition contains an inner lambda;
#  R2 the state vector is always the LAST parameter and only ever the last argument,
#     so no continuation or list cell is built where C1 would K-wrap a copy of it;
#  R3 every bit is decided in head position before a continuation is chosen;
#  R4 the next state is accumulated forward (no continuation chain inside cells).
define("snil",    r"\c n. n")
define("scons",   r"\h t c n. c h t")
define("AA_hit",  r"\rec b r2. b TRUE (rec r2)")
define("AA_miss", r"\rec b r2. rec r2")
define("AA_step", r"\c rec r. r (c AA_hit AA_miss rec) FALSE")
define("AA_fin",  r"\r. FALSE")
define("anyAnd",  r"\col r. col AA_step AA_fin r")
define("RD_step", r"\col rest k acc r. (anyAnd col r) (rest k (scons TRUE acc)) (rest k (scons FALSE acc)) r")
define("RD_fin",  r"\k acc r. k acc")
define("round",   r"\C k r. C RD_step RD_fin k snil r")
define("IT_k",    r"\rec k r2. rec TRUE k r2")
define("IT_step", r"\C x rec f k r. f (round C (IT_k rec k) r) (rec TRUE k r)")
define("IT_fin",  r"\f k r. k r")
define("iter",    r"\C k0 r0. C (IT_step C) IT_fin FALSE k0 r0")
define("P",       r"\C R T. iter C (anyAnd T) (R scons snil)")

PROGRAM = G.c1(DEFS["P"])


# ----------------------------------------------------------------- graph contract (PLACEHOLDER)
def _norm(name):
    if not isinstance(name, str) or not name:
        raise Refused("MALFORMED", f"node name {name!r}")
    return re.sub(r"[-_.]+", "-", name).lower()    # PEP 503; #150 fixes the real rule


def canonical(doc):
    """Placeholder contract: {"nodes": [...], "edges": [[u, v], ...], "roots": [...],
    "targets": [...]} -> sorted, deduplicated form, or Refused. #150 replaces this."""
    if not isinstance(doc, dict) or set(doc) != {"nodes", "edges", "roots", "targets"}:
        raise Refused("MALFORMED", "fields are not exactly nodes/edges/roots/targets")
    nodes = [_norm(x) for x in doc["nodes"]]
    if len(set(nodes)) != len(nodes):
        raise Refused("DUPLICATE_NODE")
    if not 1 <= len(nodes) <= N_MAX:
        raise Refused("LIMIT_NODES", f"{len(nodes)} nodes, admitted 1..{N_MAX}")
    known = set(nodes)

    def member(x, what):
        x = _norm(x)
        if x not in known:
            raise Refused("MISSING_NODE", f"{what} {x!r} is not an inventory node")
        return x

    edges = set()
    for e in doc["edges"]:
        if not (isinstance(e, list) and len(e) == 2):
            raise Refused("MALFORMED", f"edge {e!r}")
        edges.add((member(e[0], "edge source"), member(e[1], "edge target")))
    roots = {member(x, "root") for x in doc["roots"]}
    if not roots:
        raise Refused("NO_ROOT")
    targets = {_norm(x) for x in doc["targets"]}       # an absent target is unreachable: valid
    return {"nodes": sorted(nodes), "edges": sorted(edges), "roots": sorted(roots),
            "targets": sorted(targets & known), "targets_absent": sorted(targets - known)}


# ----------------------------------------------------------------- data terms
def _church(items):
    body = ("var", "n")
    for x in reversed(items):
        body = ("lapp", ("lapp", ("var", "c"), x), body)
    return G.c1(("lam", "c", ("lam", "n", body)))


def _bit(b):
    return TRUE_T if b else FALSE_T


def data_terms(g):
    order = g["nodes"]
    n, ix, E = len(order), {v: i for i, v in enumerate(order)}, set(g["edges"])
    cols = [_church([_bit(i == j or (order[i], order[j]) in E) for i in range(n)])
            for j in reversed(range(n))]
    C = _church(cols)
    R = _church([_bit(v in g["roots"]) for v in order])
    T = _church([_bit(v in g["targets"]) for v in order])
    del ix
    return C, R, T


def _app(*ts):
    t = ts[0]
    for u in ts[1:]:
        t = ("app", t, u)
    return t


def build(g, program=None):
    """-> (input term, identities). `program` lets a control substitute P."""
    C, R, T = data_terms(g)
    prog = PROGRAM if program is None else program
    inp = _app(prog, C, R, T)
    hx = lambda t: G.term_hash(t).hex()
    ids = {"encoder": ENCODER_ID, "program": hx(prog), "C": hx(C), "R": hx(R), "T": hx(T),
           "input": hx(inp), "graph_digest": hashlib.sha256(json.dumps(
               {k: g[k] for k in ("nodes", "edges", "roots", "targets")},
               sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    return inp, ids


def nodes_of(t):
    """Every non-genesis node of the term: the computation's environment."""
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
    """The input as sigma_provider.term() syntax (S, K, I and parentheses)."""
    out, stack = [], [t]
    names = {G.S_H: "S", G.K_H: "K", G.I_H: "I"}
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
def evaluate(inp, atp=ATP_ADMIT, limits=None):
    env = nodes_of(inp)
    t0 = time.perf_counter()
    rc = G.eval_receipt(G.term_hash(inp), atp, env, limits or G.VERIFIER_LIMITS)
    wall = time.perf_counter() - t0
    verdict = VERDICT.get(rc.result_hash) if rc.exit == "normal_form" else None
    return {"exit": rc.exit, "verdict": verdict, "result": rc.result_hash.hex(),
            "atp": rc.atp_spent, "wall_s": round(wall, 3), "env_nodes": len(env)}


def reference(g):
    """Independent traversal (the check, not the answer)."""
    adj = {}
    for u, v in g["edges"]:
        adj.setdefault(u, []).append(v)
    seen, stack = set(g["roots"]), list(g["roots"])
    while stack:
        for v in adj.get(stack.pop(), []):
            if v not in seen:
                seen.add(v)
                stack.append(v)
    return bool(seen & set(g["targets"])), sorted(seen)


# ----------------------------------------------------------------- SYNTHETIC vectors
SYNTHETIC = {
    # label: (doc, expected verdict) -- names are invented; no real wheel is described
    "SYN-pos-indirect": ({"nodes": ["app", "lib-a", "lib-b", "banned"],
                          "edges": [["app", "lib-a"], ["lib-a", "lib-b"], ["lib-b", "banned"]],
                          "roots": ["app"], "targets": ["banned"]}, True),
    "SYN-neg-present-unreached": ({"nodes": ["app", "app-extra", "lib-a", "banned"],
                                   "edges": [["app", "lib-a"], ["app-extra", "app"], ["app-extra", "banned"]],
                                   "roots": ["app"], "targets": ["banned"]}, False),
    "SYN-pos-via-extra": ({"nodes": ["app", "app-extra", "lib-a", "banned"],
                           "edges": [["app", "lib-a"], ["app-extra", "app"], ["app-extra", "banned"]],
                           "roots": ["app-extra"], "targets": ["banned"]}, True),
    "SYN-pos-cycle": ({"nodes": ["app", "x", "y", "z", "banned"],
                       "edges": [["app", "x"], ["x", "y"], ["y", "x"], ["y", "z"], ["z", "banned"]],
                       "roots": ["app"], "targets": ["banned"]}, True),
    "SYN-neg-cycle": ({"nodes": ["app", "x", "y", "banned", "w"],
                       "edges": [["app", "x"], ["x", "y"], ["y", "x"], ["w", "banned"]],
                       "roots": ["app"], "targets": ["banned"]}, False),
    "SYN-neg-target-absent": ({"nodes": ["app", "lib-a"], "edges": [["app", "lib-a"]],
                               "roots": ["app"], "targets": ["banned"]}, False),
}


def _check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    return cond


def selftest():
    ok = True
    print(f"program {G.term_hash(PROGRAM).hex()}  (C1 size {G.size(PROGRAM)})")
    for label, (doc, want) in SYNTHETIC.items():
        g = canonical(doc)
        inp, ids = build(g)
        r = evaluate(inp)
        ref, _ = reference(g)
        ok &= _check(f"{label}: Sigma {r['verdict']} == reference {ref} == expected {want}",
                     r["exit"] == "normal_form" and r["verdict"] is ref is want, r)
        print(f"       atp={r['atp']} wall={r['wall_s']}s input={ids['input'][:16]}")

    base = SYNTHETIC["SYN-pos-indirect"][0]
    g0 = canonical(base)
    _, ids0 = build(g0)
    # reordered nodes/edges/roots + spelling variants normalise to the same input
    shuffled = {"nodes": ["BANNED", "Lib_B", "lib.a", "app"],
                "edges": [["lib-b", "banned"], ["app", "lib-a"], ["lib-a", "lib-b"], ["lib-a", "lib-b"]],
                "roots": ["app"], "targets": ["banned"]}
    ok &= _check("reordered/respelled/duplicated edges -> identical input identity",
                 build(canonical(shuffled))[1]["input"] == ids0["input"])
    # a changed edge changes identity and Sigma's answer follows the reference
    cut = dict(base, edges=[["app", "lib-a"], ["lib-b", "banned"]])
    gc = canonical(cut)
    inp_c, ids_c = build(gc)
    rc = evaluate(inp_c)
    ok &= _check("changed edge: new identity, Sigma FALSE == reference",
                 ids_c["input"] != ids0["input"] and rc["verdict"] is False is reference(gc)[0], rc)
    # changed input binding: same graph, root moved -> different R identity and answer
    gr = canonical(dict(base, roots=["banned"], targets=["app"]))
    inp_r, ids_r = build(gr)
    ok &= _check("changed root/target binding: new R/T identity, Sigma FALSE == reference",
                 ids_r["R"] != ids0["R"] and evaluate(inp_r)["verdict"] is False is reference(gr)[0])
    # constant-verdict encoders: a different program identity, and blind to the cut edge
    for nm, src in (("const-TRUE", r"\C R T. TRUE"), ("const-FALSE", r"\C R T. FALSE")):
        prog = G.c1(_parse(src))
        a = evaluate(build(g0, prog)[0])["verdict"]
        b = evaluate(build(gc, prog)[0])["verdict"]
        ok &= _check(f"{nm} encoder: program identity differs from P and answers do not track the reference",
                     G.term_hash(prog) != G.term_hash(PROGRAM) and a == b and reference(g0)[0] != reference(gc)[0])
    # malformed / out-of-contract inputs are refused, never FALSE
    for nm, doc, code in (
            ("edge to a missing node", dict(base, edges=[["app", "ghost"]]), "MISSING_NODE"),
            ("root outside inventory", dict(base, roots=["ghost"]), "MISSING_NODE"),
            ("duplicate node after normalisation", dict(base, nodes=["app", "App", "lib-a", "lib-b"]), "DUPLICATE_NODE"),
            ("no root", dict(base, roots=[]), "NO_ROOT"),
            ("over the node limit", dict(base, nodes=[f"n{i}" for i in range(N_MAX + 1)], edges=[],
                                         roots=["n0"], targets=[]), "LIMIT_NODES"),
            ("unknown field", dict(base, extras=[]), "MALFORMED")):
        try:
            canonical(doc)
            got = "accepted"
        except Refused as e:
            got = e.code
        ok &= _check(f"refused, not FALSE: {nm} -> {code}", got == code, got)
    # insufficient budget is an exit, not a verdict
    inp0, _ = build(g0)
    short = evaluate(inp0, atp=1000)
    ok &= _check("insufficient budget -> atp_exhausted, no verdict",
                 short["exit"] == "atp_exhausted" and short["verdict"] is None, short)
    print("SELFTEST: " + ("ALL PASS" if ok else "FAILURES"))
    return ok


def measure(nmax=8):
    for n in range(2, nmax + 1):
        names = [f"syn{i:02d}" for i in range(n)]
        shapes = {"chain": [[names[i], names[i + 1]] for i in range(n - 1)],
                  "chain-neg": [[names[i], names[i + 1]] for i in range(n - 2)],
                  "dense-dag": [[a, b] for a in names for b in names if a < b]}
        for shape, edges in shapes.items():
            g = canonical({"nodes": names, "edges": edges, "roots": [names[0]], "targets": [names[-1]]}) \
                if n <= N_MAX else None
            if g is None:     # measuring beyond admission on purpose
                g = {"nodes": names, "edges": sorted(map(tuple, edges)), "roots": [names[0]], "targets": [names[-1]]}
            inp, ids = build(g)
            # beyond admission on purpose: the uncapped oracle limits, labelled as such
            r = evaluate(inp, 60_000_000, G.DEFAULT_LIMITS) if n > N_MAX else evaluate(inp)
            r["admitted"] = n <= N_MAX
            print(json.dumps({"n": n, "shape": shape, "edges": len(edges), **r,
                              "reference": reference(g)[0], "input": ids["input"]}), flush=True)


def provider(cases=((3, "chain"), (5, "chain"), (6, "chain"), (6, "chain-neg"))):
    """PAUSED prefix then checked foreign resume, through the installed sigma_provider."""
    import sigma_provider as SP
    import sigma_resume as RS
    for n, shape in cases:
        names = [f"syn{i:02d}" for i in range(n)]
        k = n - 1 if shape == "chain" else n - 2
        g = canonical({"nodes": names, "edges": [[names[i], names[i + 1]] for i in range(k)],
                       "roots": [names[0]], "targets": [names[-1]]})
        inp, ids = build(g)
        tm = SP.term(ski_text(inp))
        assert tm["input"] == ids["input"], "provider parse does not reproduce the identity"
        total = evaluate(inp)["atp"]
        hashes, blobs = sorted(tm["nodes"]), tm["nodes"]
        s = SP.start(RS.RUNTIME_SEMANTICS_ID, tm["input"], hashes)
        t0 = time.perf_counter()
        a = SP.advance(RS.RUNTIME_SEMANTICS_ID, hashes, blobs, s["checkpoint"], s["state"], total // 2)
        t1 = time.perf_counter()
        b = SP.resume(RS.RUNTIME_SEMANTICS_ID, tm["input"], hashes, blobs, a["checkpoint"], a["state"],
                      total - total // 2)
        t2 = time.perf_counter()
        seg = b.get("segment", {})
        ck = json.loads(seg["checkpoint"]) if seg.get("checkpoint") else None
        print(json.dumps({"n": n, "shape": shape, "input": ids["input"], "env_nodes": len(hashes),
                          "total_atp": total, "first": a["outcome"], "resume": b.get("status"),
                          "basis": b.get("base_verification", {}).get("basis"),
                          "outcome": seg.get("outcome"),
                          "verdict": VERDICT.get(bytes.fromhex(seg["result"])) if seg.get("result") else None,
                          "reference": reference(g)[0],
                          "peak_semantic_size": ck and ck.get("peak_semantic_size"),
                          "advance_wall_s": round(t1 - t0, 2), "resume_wall_s": round(t2 - t1, 2)}), flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    elif cmd == "measure":
        measure(int(sys.argv[2]) if len(sys.argv) > 2 else 8)
    elif cmd == "provider":
        provider()
    else:
        sys.exit(f"unknown command {cmd!r}")
