#!/usr/bin/env python3
"""WRT-004 reason-binding demonstration and negative controls (DESIGN ONLY).

Proves two things the proposal claims:
  (a) the justification-binding gap is REAL — a constant-equivalent term that
      ignores the policy verifies fine at base grade;
  (b) the three profile layers are CHECKABLE and each can turn red.

A green here is worth nothing until each negative is shown to fail for its
stated layer, so every negative prints the layer it must implicate.
"""
import copy
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "impl"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
import policy_lang as PL          # noqa: E402
import reason_binding_check as RB  # noqa: E402

store = {}


def put(b):
    h = hashlib.sha256(b).hexdigest()
    store[h] = b
    return h


def resolve(h):
    return store.get(h)


SOURCE = ("fact within_window: bool = true\n"
          "fact retroactive:   bool = true\n"
          "check within_window && !retroactive\n")   # -> Church FALSE -> reject

compiled = PL.compile_source(SOURCE, put=put)
src_h = put(SOURCE.encode())
prog = PL.parse(SOURCE)
manifest = {name: put(RB.fact_evidence_blob(name, f.type, f.value))
            for name, f in prog.facts.items()}

profile = {"profile": "warrant.reason-binding@v0", "check": compiled.blob,
           "policy_source": src_h, "fact_manifest": manifest,
           "decision_map": {"true": "accept", "false": "reject"}}
body = {"decision": "reject", "evidence": [src_h, *manifest.values()]}
reason = {"kind": "check", "runtime": "ski@v1", "check": compiled.blob,
          "verdict": "pass"}

results = []


def case(name, must_bind, prof=None, rsn=None, bod=None, must_mention=None):
    b, f = RB.check_binding(prof or profile, rsn or reason, bod or body, resolve)
    ok = (b == must_bind)
    if must_mention and not any(must_mention in x for x in f):
        ok = False
        f = f + [f"[control did not implicate '{must_mention}']"]
    results.append(ok)
    print(f"{'OK ' if ok else 'BAD'}  {name}: {'BOUND' if b else 'UNBOUND'}"
          + ("" if b else f"  ({f[0]})"))


# --- Positive: a correctly bound reason
case("positive (fully bound)", True)

# --- The GAP ATTACK: a term that is just the expected result (a constant),
#     reproducing expect while encoding nothing of the policy. It verifies at
#     base grade; the profile's Layer 1 must reject it.
attack_doc = {"ski": 1, "term": compiled.doc["expect"], "atp": 5,
              "expect": compiled.doc["expect"]}
import json  # noqa: E402
attack_check = put(json.dumps(attack_doc, sort_keys=True,
                              separators=(",", ":")).encode())
attack_profile = {**profile, "check": attack_check}
attack_reason = {**reason, "check": attack_check}
case("GAP ATTACK: constant term ignores policy", False,
     prof=attack_profile, rsn=attack_reason, must_mention="L1")

# --- Negative L1: swap the source so recompilation gives a different term.
alt_source = ("fact within_window: bool = true\n"
              "fact retroactive:   bool = false\n"     # different fact value
              "check within_window && !retroactive\n")
alt_src_h = put(alt_source.encode())
n1_profile = {**profile, "policy_source": alt_src_h}
n1_body = {**body, "evidence": [alt_src_h, *manifest.values()]}
case("L1 negative: source recompiles to a different term", False,
     prof=n1_profile, bod=n1_body, must_mention="L1")

# --- Negative L2: a fact's committed evidence blob lies about the value.
bad_fact = put(RB.fact_evidence_blob("within_window", "bool", False))
n2_manifest = {**manifest, "within_window": bad_fact}
n2_profile = {**profile, "fact_manifest": n2_manifest}
n2_body = {**body, "evidence": [src_h, bad_fact, manifest["retroactive"]]}
case("L2 negative: fact evidence blob contradicts the baked fact", False,
     prof=n2_profile, bod=n2_body, must_mention="L2")

# --- Negative L3: decision inconsistent with the mapped result.
n3_body = {**body, "decision": "accept"}   # result is FALSE -> map says reject
case("L3 negative: decision contradicts result->decision map", False,
     bod=n3_body, must_mention="L3")

print(f"\n{sum(results)}/{len(results)} cases correct "
      "(positive binds; gap attack + each layer's negative turns red for its "
      "own layer).")
sys.exit(0 if all(results) else 1)
