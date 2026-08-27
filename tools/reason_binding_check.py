#!/usr/bin/env python3
"""Prototype checker for the WRT-004 reason-binding profile (DESIGN ONLY).

This is NOT part of `warrant verify` and changes no SPEC surface. It exists so
that WRT-004's central claim — that the justification-binding gap (NG-7) is
*checkable* — is demonstrated by a running program rather than asserted in
prose, per this repository's "no prose without a vector" discipline.

The gap (NG-7): the core format verifies that a `ski@v1` term re-executes to
its declared result, but never that the term IS the pinned policy over the
cited evidence yielding a result consistent with the decision. A filer can
attach a term equivalent to a constant that reproduces its own `expect`; base
verification is happy; nothing semantic is bound.

The profile is a blob cited in `evidence`:

    { "profile": "warrant.reason-binding@v0",
      "check":         "<hex64 ski@v1 check blob the reason cites>",
      "policy_source": "<hex64 WPL source blob>",
      "fact_manifest": { "<fact name>": "<hex64 fact-evidence blob>", ... },
      "decision_map":  { "true": "<decision>", "false": "<decision>" } }

`check_binding` returns (bound: bool, findings: list[str]). It checks three
layers, and is scrupulous about what it does NOT establish (see WRT-004 §4):
it does not prove a fact is *true* (SA-11), nor that the policy is a *good*
policy (NG-4); it proves the term is this policy's compilation, that each
baked-in fact is committed as a named hash-pinned evidence item, and that the
result maps to the decision under a committed map.
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "impl"))
import policy_lang as PL  # noqa: E402


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def fact_evidence_blob(name, ftype, value):
    """Canonical bytes committing one WPL fact as a named evidence item.
    JCS-canonical, integers-only — the same domain as every other trust blob."""
    return PL._canon({"fact": name, "type": ftype, "value": value})


def check_binding(profile, reason, body, resolve):
    """profile: the parsed reason-binding blob (dict).
    reason:  the `because[]` check entry the profile binds (dict).
    body:    the warrant body (dict), for `evidence` and `decision`.
    resolve: callable hex64 -> bytes | None (the blob store).
    Returns (bound, findings)."""
    findings = []

    if profile.get("profile") != "warrant.reason-binding@v0":
        return False, ["not a warrant.reason-binding@v0 profile"]
    if reason.get("runtime") != "ski@v1":
        return False, ["reason-binding applies to ski@v1 reasons only"]
    if reason.get("check") != profile.get("check"):
        return False, ["profile.check does not match the reason's check hash"]

    # Resolve the ski check blob the reason cites, to read its term/expect.
    check_bytes = resolve(reason["check"])
    if check_bytes is None:
        return False, ["ski check blob does not resolve"]
    try:
        check_doc = json.loads(check_bytes)
    except ValueError:
        return False, ["ski check blob is not JSON"]

    # Resolve the WPL policy source.
    src_hex = profile.get("policy_source")
    src_bytes = resolve(src_hex) if src_hex else None
    if src_bytes is None:
        return False, ["policy_source blob does not resolve"]
    if src_hex not in body.get("evidence", []):
        findings.append("policy_source is not listed in the record's evidence")
    try:
        source = src_bytes.decode("utf-8")
        prog = PL.parse(source)
    except (UnicodeDecodeError, PL.PolicyError) as exc:
        return False, [f"policy_source is not valid WPL: {exc}"]

    # ---- Layer 1: the term IS the compilation of this exact policy source.
    try:
        compiled = PL.compile_source(source, put=lambda b: sha256_hex(b))
    except PL.PolicyError as exc:
        return False, [f"policy_source does not compile: {exc}"]
    if compiled.term != check_doc.get("term"):
        findings.append("L1: the check's term is NOT the compilation of "
                        "policy_source (the term does not encode this policy)")
    if compiled.doc["expect"] != check_doc.get("expect"):
        findings.append("L1: the check's expect does not match the policy's "
                        "compiled result")

    # ---- Layer 2: every baked-in fact is a named, hash-pinned evidence item.
    manifest = profile.get("fact_manifest", {})
    ev = set(body.get("evidence", []))
    src_facts = set(prog.facts)
    if set(manifest) != src_facts:
        findings.append(f"L2: fact_manifest keys {sorted(manifest)} do not "
                        f"equal the policy's facts {sorted(src_facts)}")
    for name, f in prog.facts.items():
        h = manifest.get(name)
        if h is None:
            findings.append(f"L2: fact '{name}' has no manifest entry")
            continue
        want = fact_evidence_blob(name, f.type, f.value)
        got = resolve(h)
        if got is None:
            findings.append(f"L2: fact '{name}' evidence blob {h[:12]} "
                            "does not resolve")
        elif got != want:
            findings.append(f"L2: fact '{name}' evidence blob content does not "
                            "match the fact baked into the term "
                            "(name/type/value)")
        if h not in ev:
            findings.append(f"L2: fact '{name}' evidence blob is not listed in "
                            "the record's evidence")

    # ---- Layer 3: the result maps to the decision under a committed map.
    dm = profile.get("decision_map", {})
    key = "true" if compiled.result else "false"
    mapped = dm.get(key)
    if mapped is None:
        findings.append(f"L3: decision_map has no entry for result={key}")
    elif mapped != body.get("decision"):
        findings.append(f"L3: result={key} maps to '{mapped}' but the record's "
                        f"decision is '{body.get('decision')}'")

    return (len(findings) == 0), findings


def _demo():
    """Self-contained positive check, so the module runs green standalone."""
    store = {}

    def put(b):
        h = sha256_hex(b)
        store[h] = b
        return h

    def resolve(h):
        return store.get(h)

    source = ("fact within_window: bool = true\n"
              "fact retroactive:   bool = true\n"
              "check within_window && !retroactive\n")
    compiled = PL.compile_source(source, put=put)
    src_h = put(source.encode())
    prog = PL.parse(source)
    manifest = {}
    for name, f in prog.facts.items():
        manifest[name] = put(fact_evidence_blob(name, f.type, f.value))
    profile = {"profile": "warrant.reason-binding@v0", "check": compiled.blob,
               "policy_source": src_h, "fact_manifest": manifest,
               "decision_map": {"true": "accept", "false": "reject"}}
    body = {"decision": "reject",
            "evidence": [src_h, *manifest.values()]}
    reason = {"kind": "check", "runtime": "ski@v1", "check": compiled.blob,
              "verdict": "pass"}
    bound, findings = check_binding(profile, reason, body, resolve)
    print("reason-binding self-demo:", "BOUND" if bound else "UNBOUND")
    for f in findings:
        print("  -", f)
    return bound


if __name__ == "__main__":
    sys.exit(0 if _demo() else 1)
