#!/usr/bin/env python3
"""Check the published JSON Schemas against this repository's own corpus.

WHY THIS EXISTS
---------------
Publishing schema files is cheap and publishing schema files that have drifted
from the vectors is worse than publishing none: a third-party tool validates
against them, gets a green tick, and has learned nothing about whether its
record verifies. So the schemas are checked in BOTH directions, every run:

  * every positive artifact in examples/ and demos/ MUST validate;
  * every SPEC §8.3 negative body MUST NOT validate (a schema that accepts a
    MUST-REJECT vector is a defect in the schema, not a tolerable gap);
  * every case in examples/canon-vectors.json MUST validate as a body, so the
    canonicalization battery and the schema cannot disagree about what a legal
    body is;
  * live `verify --json` output from the reference implementation MUST validate
    against verify-report-v0.schema.json, so the schema tracks the producer.

WHAT A GREEN RUN DOES NOT MEAN
------------------------------
Passing a schema is NECESSARY AND NOT SUFFICIENT for conformance (SPEC §14.2).
JSON Schema cannot express canonicalization, duplicate-member rejection,
signature acceptance, ski@v1 re-execution, or settlement. Four §8.3 negative
vectors are expected to be UNCATCHABLE by schema alone and are listed by name
below rather than quietly dropped -- an exclusion list you cannot see is how a
suite ends up asserting nothing.

THE VALIDATOR
-------------
This repository has zero runtime dependencies in every implementation, and
`jsonschema` is not installed in its CI. So: if `jsonschema` is importable it is
used (the stronger check, and it is reported by name); otherwise a small
built-in validator covering exactly the draft-2020-12 keywords these schemas use
runs instead. The built-in one is deliberately STRICT about its own coverage --
it raises on a keyword it does not implement, so a schema written with a keyword
the checker silently ignores cannot pass by accident. That failure mode is the
whole reason this file is not fifteen lines long.

USAGE
    python3 tools/schema_check.py           # one verdict
    python3 tools/schema_check.py -v        # per-artifact lines
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"

# ---------------------------------------------------------------- validator --

SUPPORTED = {
    "$schema", "$id", "$ref", "$defs", "title", "description", "type", "enum",
    "const", "properties", "required", "additionalProperties", "propertyNames",
    "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength",
    "pattern", "minimum", "maximum", "allOf", "anyOf", "oneOf", "not",
    "if", "then", "else",
}

TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "number": (int, float), "integer": int, "null": type(None),
}


class Unsupported(Exception):
    """A schema used a keyword this checker does not implement. Loud on purpose:
    silently ignoring a keyword turns a constraint into decoration."""


def _type_ok(value, name):
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py = TYPES.get(name)
    if py is None:
        raise Unsupported(f"type {name!r}")
    if py is str or py is list or py is dict:
        return isinstance(value, py)
    return isinstance(value, py)


def _resolve(ref, root, registry):
    if ref.startswith("#/"):
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        return node, root
    if ref in registry:
        return registry[ref], registry[ref]
    raise Unsupported(f"$ref {ref!r} (not local and not a known schema $id)")


def validate(value, schema, root=None, registry=None, path="$"):
    """Return a list of error strings; [] means valid."""
    root = schema if root is None else root
    registry = registry or {}
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: schema is false"]
    for k in schema:
        if k not in SUPPORTED:
            raise Unsupported(f"keyword {k!r} at {path}")
    e = []
    if "$ref" in schema:
        sub, subroot = _resolve(schema["$ref"], root, registry)
        e += validate(value, sub, subroot, registry, path)
    if "type" in schema:
        names = schema["type"]
        names = [names] if isinstance(names, str) else names
        if not any(_type_ok(value, n) for n in names):
            e.append(f"{path}: type is not {schema['type']}")
            return e
    if "enum" in schema and value not in schema["enum"]:
        e.append(f"{path}: {value!r} not in enum")
    if "const" in schema and value != schema["const"]:
        e.append(f"{path}: {value!r} != const {schema['const']!r}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            e.append(f"{path}: shorter than minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            e.append(f"{path}: longer than maxLength")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            e.append(f"{path}: does not match pattern {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            e.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            e.append(f"{path}: above maximum")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            e.append(f"{path}: fewer than minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            e.append(f"{path}: more than maxItems")
        if schema.get("uniqueItems") and len(
                {json.dumps(x, sort_keys=True) for x in value}) != len(value):
            e.append(f"{path}: items are not unique")
        if "items" in schema:
            for i, item in enumerate(value):
                e += validate(item, schema["items"], root, registry, f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                e.append(f"{path}: missing required member {req!r}")
        if "propertyNames" in schema:
            for k in value:
                e += validate(k, schema["propertyNames"], root, registry, f"{path}.<key {k!r}>")
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                e += validate(v, props[k], root, registry, f"{path}.{k}")
            elif extra is False:
                e.append(f"{path}: unknown member {k!r}")
            elif extra is not True:
                e += validate(v, extra, root, registry, f"{path}.{k}")
    for kw in ("allOf",):
        for sub in schema.get(kw, []):
            e += validate(value, sub, root, registry, path)
    if "anyOf" in schema and not any(
            not validate(value, s, root, registry, path) for s in schema["anyOf"]):
        e.append(f"{path}: matches no branch of anyOf")
    if "oneOf" in schema:
        n = sum(1 for s in schema["oneOf"]
                if not validate(value, s, root, registry, path))
        if n != 1:
            e.append(f"{path}: matches {n} branches of oneOf, want exactly 1")
    if "not" in schema and not validate(value, schema["not"], root, registry, path):
        e.append(f"{path}: matches 'not'")
    if "if" in schema:
        matched = not validate(value, schema["if"], root, registry, path)
        branch = schema.get("then") if matched else schema.get("else")
        if branch is not None:
            e += validate(value, branch, root, registry, path)
    return e


# ------------------------------------------------------------------ harness --

FAILS = []
VERBOSE = "-v" in sys.argv[1:]
USING = "built-in (stdlib only)"

try:
    import jsonschema as _js
    USING = f"jsonschema {_js.__version__}"
except Exception:
    _js = None


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


REGISTRY = {}


def load_schemas():
    for p in sorted(SCHEMAS.glob("*.json")):
        s = load(p)
        REGISTRY[s["$id"]] = s
    return REGISTRY


def errors_for(value, schema):
    if _js is not None:
        resolver = _js.RefResolver.from_schema(schema, store=dict(REGISTRY))
        v = _js.Draft202012Validator(schema, resolver=resolver)
        return [e.message for e in v.iter_errors(value)]
    return validate(value, schema, registry=REGISTRY)


def check(name, cond, detail=""):
    if cond:
        if VERBOSE:
            print(f"OK   {name}")
    else:
        print(f"FAIL {name}  <<< {detail}")
        FAILS.append(name)
    return cond


def must_validate(name, value, schema):
    errs = errors_for(value, schema)
    return check(name, not errs, "; ".join(errs[:3]))


def must_not_validate(name, value, schema):
    errs = errors_for(value, schema)
    return check(name, bool(errs), "schema ACCEPTED a MUST-REJECT vector")


# Rejection classes SPEC §8.3 names that live BELOW the schema layer, so no JSON
# Schema can express them and the cross-implementation harnesses own them
# instead. Printed every run rather than dropped: an exclusion you cannot see is
# how a suite ends up asserting less than a reader thinks.
SCHEMA_BLIND = {
    "duplicate member names (§4)":
        "a parsed dict has already lost the duplicate -- tests/hostile.py",
    "trailing content after the JSON value (§4)":
        "the schema never sees the bytes -- tests/hostile.py",
    "non-JCS-canonical blob bytes (§4)":
        "canonical form is a byte property, not a value property -- tests/differential.py",
    "small-order / non-canonical Ed25519 keys (§5)":
        "a 64-hex string is a 64-hex string -- examples/conformance-negatives.json",
}


def main():
    load_schemas()
    body_s = REGISTRY["https://github.com/s0fractal/warrant/schemas/warrant-body.schema.json"]
    env_s = REGISTRY["https://github.com/s0fractal/warrant/schemas/warrant-envelope.schema.json"]
    rep_s = REGISTRY["https://github.com/s0fractal/warrant/schemas/verify-report-v0.schema.json"]
    trust_s = REGISTRY["https://github.com/s0fractal/warrant/schemas/trust-config.schema.json"]
    man_s = REGISTRY["https://github.com/s0fractal/warrant/schemas/evidence-pack-manifest.schema.json"]

    print(f"schema_check: validator = {USING}")

    # 1. Every stored envelope in the repository validates (SPEC §8 vectors, the
    #    ski@v1 vector, the demo packs, and this repository's own store).
    envelopes = sorted(ROOT.glob("examples/*.warrant.json"))
    envelopes += sorted(ROOT.glob("examples/ski/*.warrant.json"))
    envelopes += sorted(ROOT.glob("demos/*/pack/.warrants/records/*.json"))
    envelopes += sorted(ROOT.glob(".warrants/records/*.json"))
    check("corpus is non-empty (envelopes)", len(envelopes) >= 5, f"{len(envelopes)} found")
    for p in envelopes:
        env = load(p)
        must_validate(f"envelope {p.relative_to(ROOT)}", env, env_s)
        must_validate(f"body     {p.relative_to(ROOT)}", env["body"], body_s)

    # 2. The canonicalization battery (§8.4): every case body is a legal body, so
    #    the schema and the canon vectors cannot disagree about what is legal.
    #    Both directions: `schema_valid` in the vector file is the reference
    #    implementation's verdict, so this compares the PUBLISHED SCHEMA against
    #    the REFERENCE VALIDATOR on 48 adversarial bodies. Two of them (a
    #    201-code-point note and a free-key UTF-16 ordering probe) are
    #    canonical-and-schema-invalid on purpose, which is
    #    what makes this a two-directional check rather than a formality.
    cv = load(ROOT / "examples" / "canon-vectors.json")
    check("canon vectors present", len(cv["cases"]) >= 45, str(len(cv["cases"])))
    check("canon vectors include a schema-INVALID case (two-directional)",
          any(not c["schema_valid"] for c in cv["cases"]))
    for c in cv["cases"]:
        if c["schema_valid"]:
            must_validate(f"canon-vector body {c['name']}", c["body"], body_s)
        else:
            must_not_validate(f"canon-vector body {c['name']} (schema-invalid)",
                              c["body"], body_s)

    # 3. §8.3 negatives: the schema MUST reject every schema_invalid body. This is
    #    the direction that actually tests the schema -- a permissive schema passes
    #    every positive corpus and is worthless.
    neg = load(ROOT / "examples" / "conformance-negatives.json")
    for i, item in enumerate(neg["schema_invalid"]):
        body = item["body"] if isinstance(item, dict) and "body" in item else item
        label = (item.get("why") or item.get("note") or f"#{i}") if isinstance(item, dict) else f"#{i}"
        must_not_validate(f"negative body [{label}]", body, body_s)
    for name, why in SCHEMA_BLIND.items():
        print(f"NOTE not schema-expressible: {name} -- {why}")

    # 4. The report schema against LIVE producer output, not a hand-written
    #    sample: the schema must track what the implementation actually emits.
    for args, label in (
        (["--store", str(ROOT / ".warrants"), "verify", "--store-mode", "--json"], "own store"),
        (["--store", str(ROOT / "demos/air-canada/pack/.warrants"), "verify",
          "--store-mode", "--json"], "air-canada pack"),
        (["--store", str(ROOT / "does-not-exist"), "verify", "--store-mode", "--json"],
         "no store (fail-closed)"),
    ):
        r = subprocess.run([sys.executable, str(ROOT / "impl" / "warrant.py")] + args,
                           capture_output=True, text=True)
        try:
            rep = json.loads(r.stdout)
        except ValueError:
            check(f"report {label}: one JSON object", False, repr(r.stdout[:120]))
            continue
        must_validate(f"report {label}", rep, rep_s)
        # §11.1 counts-bind-findings and ok-binds-errors: NOT expressible in JSON
        # Schema, so they are checked here rather than assumed by the schema's
        # green tick.
        errs = sum(1 for f in rep["findings"] if f["level"] == "ERR")
        warns = sum(1 for f in rep["findings"] if f["level"] == "WARN")
        check(f"report {label}: counts bind findings (§11.1, not schema-expressible)",
              rep["errors"] == errs and rep["warnings"] == warns,
              f"errors={rep['errors']}/{errs} warnings={rep['warnings']}/{warns}")
        check(f"report {label}: ok == (errors == 0)", rep["ok"] == (rep["errors"] == 0))
    # A drifted producer must be caught: the schema has teeth only if it rejects.
    good = {"report": "warrant.verify-report@v0", "grade": "base", "ok": True,
            "records": 0, "errors": 0, "warnings": 0, "findings": []}
    must_validate("report baseline validates", good, rep_s)
    for label, bad in {
        "extra top-level key": {**good, "extra": 1},
        "missing key": {k: v for k, v in good.items() if k != "grade"},
        "INFO level": {**good, "findings": [{"level": "INFO", "subject": "x", "message": "y"}]},
        "finding extra key": {**good, "findings": [{"level": "ERR", "subject": "x",
                                                    "message": "y", "code": 9}]},
        "wrong tag": {**good, "report": "warrant.verify-report@v1"},
        "unknown grade": {**good, "grade": "settlement-grade"},
    }.items():
        must_not_validate(f"report schema rejects: {label}", bad, rep_s)

    # 5. Trust config: the shipped one, plus the nested-type shapes that once
    #    crashed Python while Go returned zero errors (SPEC §12.2).
    must_validate("trust-config.json (shipped)", load(ROOT / "trust-config.json"), trust_s)
    must_validate("trust config {} is valid", {}, trust_s)
    for label, bad in {
        "actors is an array": {"actors": []},
        "actor keys not a list": {"actors": {"a": 1}},
        "actor key not hex64": {"actors": {"a": ["zz"]}},
        "empty actor id": {"actors": {"": ["0" * 64]}},
        "unknown member": {"nope": 1},
        "genesis_roots not hex64": {"genesis_roots": ["short"]},
        "genesis_json_sha256 not hex64": {"genesis_json_sha256": 7},
    }.items():
        must_not_validate(f"trust config rejects: {label}", bad, trust_s)

    # 6. Evidence-pack manifests: the shipped packs, and the one required member.
    mans = sorted(ROOT.glob("demos/*/pack/manifest.json"))
    check("manifest corpus is non-empty", bool(mans), "no demo manifests found")
    for p in mans:
        must_validate(f"manifest {p.relative_to(ROOT)}", load(p), man_s)
    must_not_validate("manifest rejects: wrong format version", {"evidence_pack": "1"}, man_s)
    must_not_validate("manifest rejects: missing evidence_pack", {"title": "x"}, man_s)
    # Deliberately OPEN (EVIDENCE-PACK.md): an unknown member is allowed here and
    # nowhere else in this project. Asserted so the exception stays deliberate.
    must_validate("manifest allows unknown members (deliberate, EVIDENCE-PACK.md)",
                  {"evidence_pack": "0", "future_field": {"x": 1}}, man_s)

    print()
    if FAILS:
        print(f"SCHEMA-CHECK: {len(FAILS)} FAIL(S): " + ", ".join(FAILS[:6])
              + (" ..." if len(FAILS) > 6 else ""))
        return 1
    print(f"SCHEMA-CHECK: ALL PASS ({USING}); "
          "passing a schema is necessary and NOT sufficient (SPEC §14.2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
