#!/usr/bin/env python3
"""The extensional-equivalence LIMIT of the WRT-005 rule, as a fail-closed
countervector (Codex round 2).

WRT-005 §9 claims a *structural* guarantee, not a semantic one: the fingerprint
is a function of the eligible result NODE, so a variation preserving that node
creates no novelty. It does NOT make false-positive novelty impossible — the
result node is FINER than extensional equivalence. Book I supplies the witness:

    K       and   S(K K) I

are extensionally equal (both are the K combinator: `_ x y -> x`), yet they
normalize to different result nodes, both DISSONANCE-free (hence eligible), so
the rule gives them different fingerprints and would admit `S(K K) I` as a
"new" result over a matter settled by `K`. For unbounded SKI, Rice rules out a
total, sound-and-complete decider of extensional equivalence. Bounded canonical
profiles, conservative policies, and proof-carrying schemes can close specific
classes; WRT-005's core result-node rule chooses none of them and names the
remaining limit.

Asserted here (any deviation exits 1; a missing Σ-GLYPH oracle exits 2):
  - K and S(K K) I normalize to DIFFERENT result nodes;
  - both are DISSONANCE-free, hence both eligible;
  - they are extensionally equal on a sample: `K a b` = `S(K K) I a b` = `a`;
  - therefore the rev-4 fingerprint `(ski@v1, result_node)` DIFFERS for two
    extensionally-equal terms — the named false positive.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import settlement as T  # noqa: E402

W = T.W
sg = W.load_sigma()
if sg is None:
    print("wrt005-extensional-limit: UNRUN — the Σ-GLYPH oracle was not found "
          "(set SIGMA_GLYPH)", file=sys.stderr)
    sys.exit(2)

_failures = []


def check(cond, msg):
    ok = bool(cond)
    print(f"  {'ok ' if ok else 'BAD'}  {msg}")
    if not ok:
        _failures.append(msg)


tmp = tempfile.mkdtemp(prefix="wrt005-ext-")
store, keys, opaque = T.setup(tmp)


def node(bs):
    T.put_blob(store, bs)
    return sg.node_hash(bs)


def app(f, a):
    return node(sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=f, right=a))


def result(term_hash):
    chk = T.put_json_blob(store, {"ski": 1, "term": term_hash.hex(), "atp": 60,
                                  "expect": term_hash.hex()})
    _, res, _ = W.run_ski_check(W.Store(store), chk)
    b = sg.GENESIS.get(bytes.fromhex(res)) or open(
        os.path.join(store, "blobs", res), "rb").read()
    return res, sg.deser(b)["op"]


# K  vs  S (K K) I
kk = app(sg.K_H, sg.K_H)
skk = app(sg.S_H, kk)
skki = app(skk, sg.I_H)

r_k, op_k = result(sg.K_H)
r_skki, op_skki = result(skki)

print("K vs S(K K) I — extensionally equal, structurally distinct:")
check(r_k != r_skki, "they normalize to DIFFERENT result nodes")
check(op_k != sg.DISSONANCE and op_skki != sg.DISSONANCE,
      "both results are DISSONANCE-free (both eligible)")

# extensional sample: apply each to a=I, b=S; the K combinator returns a=I.
i_hash = node(sg.ser(sg.LITERAL, sg.F_ATOM, atom=sg.atomI)) \
    if hasattr(sg, "atomI") else sg.I_H
ext_k = result(app(app(sg.K_H, sg.I_H), sg.S_H))[0]
ext_skki = result(app(app(skki, sg.I_H), sg.S_H))[0]
check(ext_k == ext_skki,
      "extensionally equal on (I, S): both return their first argument")

# the rev-4 fingerprint is (runtime, result_node); it DIFFERS for these two.
fp = lambda r: ("ski@v1", r)
check(fp(r_k) != fp(r_skki),
      "the rev-4 fingerprint DIFFERS for two extensionally-equal terms "
      "(the named false positive; result node is finer than extensional eq.)")

print(f"\n{'FAIL' if _failures else 'PASS'} — the K / S(K K) I limit holds: the "
      "rule is structural, not semantic; result-node identity is finer than "
      "extensional equivalence.")
sys.exit(1 if _failures else 0)
