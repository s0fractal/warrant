"""Runs inside the provider interpreter (see warrant/compute.py). It is never
imported by the assessing process. The pinned kernel modules are already loaded
from checked bytes when `main` is called; nothing here reads a file."""
import base64
import json
import sys

G = sys.modules["sigma_glyph"]
R = sys.modules["sigma_resume"]

ATOMS = {"S": G.S_H, "K": G.K_H, "I": G.I_H, "Y": R.Y_H, "M": R.M_H, "W": R.W_H}


class Delivered:
    def __init__(self, blobs):
        self.blobs = blobs

    def get(self, h):
        return self.blobs.get(h.hex())


def _env(args, blobs):
    return R.Environment([bytes.fromhex(h) for h in args["hashes"]], Delivered(blobs))


def _root(args, env):
    return R.root(bytes.fromhex(args["input"]), env, args["runtime"])


def parse(expr):
    """`S K (K I)`, `#<hex64>` for a stored node: applications associate left."""
    toks = expr.replace("(", " ( ").replace(")", " ) ").split()
    pos = 0

    def atom():
        nonlocal pos
        if pos >= len(toks):
            raise ValueError("unexpected end of term")
        t = toks[pos]
        pos += 1
        if t == "(":
            v = seq()
            if pos >= len(toks) or toks[pos] != ")":
                raise ValueError("unbalanced parentheses")
            pos += 1
            return v
        if t in ATOMS:
            return ("thunk", ATOMS[t])
        if t.startswith("#") and len(t) == 65:
            return ("thunk", bytes.fromhex(t[1:]))
        raise ValueError(f"unknown token {t!r}")

    def seq():
        v = atom()
        while pos < len(toks) and toks[pos] != ")":
            v = ("app", v, atom())
        return v

    v = seq()
    if pos != len(toks):
        raise ValueError("trailing tokens")
    return v


def _nodes(t, out):
    if t[0] == "app":
        _nodes(t[1], out)
        _nodes(t[2], out)
        b = G.term_bytes(t)
        out[G.node_hash(b).hex()] = b


def op_term(args, blobs):
    t = parse(args["expr"])
    nodes = {}
    _nodes(t, nodes)
    return {"term": G.term_hash(t).hex(), "nodes": {h: base64.b64encode(b).decode() for h, b in nodes.items()}}


def _result(state_bytes):
    _, term = R.decode_state(state_bytes)
    return G.term_hash(term).hex()


def op_start(args, blobs):
    env = _env(args, blobs)
    _, cid = _root(args, env)
    doc, _, sb = R.start(cid, bytes.fromhex(args["input"]))
    return {"checkpoint": base64.b64encode(R._canon(doc)).decode(), "state": base64.b64encode(sb).decode(),
            "outcome": "STARTED"}


def op_advance(args, blobs):
    env = _env(args, blobs)
    ck_raw = base64.b64decode(args["checkpoint"])
    doc, ck_id = R.parse_checkpoint(ck_raw)
    sb = base64.b64decode(args["state"])
    res = R.advance(doc, ck_id, sb, env, args["credit"], runtime=args["runtime"],
                    max_actions=args.get("max_actions"))
    out = {"outcome": res.outcome, "checkpoint": base64.b64encode(R._canon(res.checkpoint)).decode(),
           "state": base64.b64encode(res.state_bytes).decode(), "missing": res.missing}
    if res.outcome == R.NORMAL_FORM:
        out["result"] = _result(res.state_bytes)
    return out


def op_verify(args, blobs):
    """Verify each (checkpoint, state) in order; with `cache`, later ones may start
    from an earlier verified checkpoint. The answer must not depend on it."""
    env = _env(args, blobs)
    root = _root(args, env)
    cache = R.VerifiedCache() if args.get("cache") else None
    out = []
    for ck, st in args["chain"]:
        sb = base64.b64decode(st)
        basis, code, _ = R.verify(root, env, base64.b64decode(ck), sb, cache=cache)
        r = {"basis": basis, "code": code}
        if basis == R.REPLAYED and code == R.NORMAL_FORM:
            r["result"] = _result(sb)
        out.append(r)
    return {"results": out, "verifier": R.VERIFIER_ID}


def op_find_cycle(args, blobs):
    """Producer side: step one action at a time until a machine state repeats."""
    env = _env(args, blobs)
    _, cid = _root(args, env)
    doc, ck_id, sb = R.start(cid, bytes.fromhex(args["input"]))
    seen = {}
    for _ in range(args["max_steps"]):
        sid = R.state_id(sb)
        if sid in seen:
            e_doc, e_sb, e_actions = seen[sid]
            spent = doc["spent_total"] - e_doc["spent_total"]
            actions = len(seen) - e_actions
            w = R.cycle_witness(cid, e_doc, e_sb, actions, spent)
            return {"witness": base64.b64encode(R._canon(w)).decode()}
        seen[sid] = (doc, sb, len(seen))
        res = R.advance(doc, ck_id, sb, env, 1_000_000, runtime=args["runtime"], max_actions=1)
        if res.outcome not in (R.PAUSED, R.INCOMPLETE) and res.checkpoint["transition_claim"]["actions"] == 0:
            return {"witness": None, "outcome": res.outcome}
        doc, ck_id, sb = dict(res.checkpoint, credit_total=res.checkpoint["spent_total"]), res.checkpoint_id, res.state_bytes
    return {"witness": None, "outcome": "NO_CYCLE_WITHIN_LIMIT"}


def op_verify_cycle(args, blobs):
    env = _env(args, blobs)
    witness = json.loads(base64.b64decode(args["witness"]))
    return {"code": R.verify_cycle(_root(args, env), env, witness), "verifier": R.VERIFIER_ID}


OPS = {"term": op_term, "start": op_start, "advance": op_advance, "verify": op_verify,
       "find_cycle": op_find_cycle, "verify_cycle": op_verify_cycle}


def main(req):
    blobs = {h: base64.b64decode(b) for h, b in req.get("blobs", {}).items()}
    try:
        return OPS[req["op"]](req["args"], blobs)
    except (R.InvalidEncoding, R.IntegerOverflow, ValueError, KeyError, TypeError) as e:
        return {"refused": f"{type(e).__name__}: {e}"}
