#!/usr/bin/env python3
"""WRT-007 reproducer (rev 3): does a candidate evaluator match what a Warrant release selected for a tag,
and does it conform to the tag's normative vector manifest?

Bindings verified before anything runs (each a named refusal):
  registry closed schema (recursive, typed)     manifest closed schema (recursive, typed)
  manifest.registry_sha256 == sha256(registry)  manifest.selected_runtime_record_commitment == commit(registry[tag])
  registry[tag].semantics.spec_sha256 == sha256(SPEC.md @ spec_commit)   (live git binding)
  tag registered; evaluator ACTIVE (candidates are inert and never used)
  examples/ski/* == registry[tag].vector_manifest.warrant_ski_specimen (exact closed map)
  sha256(candidate module) == manifest module_sha256                     (BEFORE any import)
Axes: artifact_identity | module_identity | semantic_conformance (WRT-006 receipt embedded; its core_sha256
must equal manifest.conformance_receipt_sha256). credit_bearing is true ONLY if every binding holds, the
records are the repository defaults, AND manifest.activation.status == "active" with a named act.
Writes nothing.
"""
import argparse, hashlib, json, os, subprocess, sys, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
DEF_REG, DEF_MAN = os.path.join(HERE, "runtime-registry.json"), os.path.join(HERE, "release-evaluator-manifest.json")

def sha_b(b): return hashlib.sha256(b).hexdigest()
def sha(p): return sha_b(open(p, "rb").read())
def commit(o): return sha_b(json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
def is_hex64(x): return isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)
def hex_or_null(x): return x is None or is_hex64(x)
def str_or_null(x): return x is None or isinstance(x, str)
def is_str(x): return isinstance(x, str)
def is_int(x): return isinstance(x, int) and not isinstance(x, bool)
def enum(*vals): return lambda x: x in vals
def list_of_str(x): return isinstance(x, list) and all(isinstance(i, str) for i in x)
def hexmap(x): return isinstance(x, dict) and all(isinstance(k, str) and is_hex64(v) for k, v in x.items())

# Recursive closed schemas: dict → exact keys with validators (a validator may itself be a dict schema).
SUITE = {"ref": is_str, "format_version": is_int, "sha256": hex_or_null, "required_fields": list_of_str}
VM = {"sigma_book1_suite": SUITE, "warrant_ski_specimen": {"path": is_str, "files_sha256": hexmap}}
SEM = {"text": is_str, "spec_path": is_str, "spec_sections": list_of_str, "spec_commit": str_or_null, "spec_sha256": hex_or_null}
STORE = {"rule": is_str, "spec_sha256": is_hex64, "enforced_by": is_str, "test_path": is_str, "test_sha256": is_hex64}
TAG = {"status": enum("registered", "unregistered"), "semantics": SEM, "body_versions": list_of_str, "vector_manifest": VM,
       "vector_manifest_commitment": is_hex64, "store_contract": STORE}
REG = {"schema": enum("warrant/runtime-registry@draft-1"), "note": is_str, "tags": lambda x: isinstance(x, dict)}
ART = {"distribution": is_str, "version": is_str, "wheel_filename": is_str, "wheel_sha256": hex_or_null, "note": is_str}
EVAL = {"selection_status": enum("active", "candidate"), "form": enum("vendored-file", "distribution"), "module": is_str, "module_sha256": is_hex64,
        "artifact": ART, "selected_runtime_record_commitment": is_hex64, "conformance_receipt_sha256": hex_or_null, "conformance_note": is_str}
MAN = {"schema": enum("warrant/release-evaluator-manifest@draft-1"), "note": is_str,
       "warrant_release": {"commit": is_hex64 if False else is_str, "tag": str_or_null, "status": is_str},
       "registry_ref": is_str, "registry_sha256": is_hex64,
       "activation": {"status": enum("draft", "active"), "act": str_or_null, "note": is_str},
       "evaluators": lambda x: isinstance(x, dict), "candidates": lambda x: isinstance(x, dict)}


def validate(obj, schema, where):
    if isinstance(schema, dict):
        if not isinstance(obj, dict): raise ValueError(f"{where}: expected object")
        extra, missing = set(obj) - set(schema), set(schema) - set(obj)
        if extra or missing: raise ValueError(f"{where}: closed schema violated (extra={sorted(extra)}, missing={sorted(missing)})")
        for k, sub in schema.items(): validate(obj[k], sub, f"{where}.{k}")
    else:
        if not schema(obj): raise ValueError(f"{where}: invalid value {obj!r}")


def validate_registry(r):
    validate(r, REG, "registry")
    for t, rec in r["tags"].items():
        validate(rec, TAG, f"registry.tags[{t}]")
        if rec["vector_manifest_commitment"] != commit(rec["vector_manifest"]): raise ValueError(f"registry.tags[{t}]: vector_manifest_commitment does not match")
        if rec["status"] == "registered" and (rec["semantics"]["spec_commit"] is None or rec["semantics"]["spec_sha256"] is None):
            raise ValueError(f"registry.tags[{t}]: a registered tag must bind exact SPEC bytes")


def validate_manifest(m):
    validate(m, MAN, "manifest")
    for grp, want in (("evaluators", "active"), ("candidates", "candidate")):
        for t, rec in m[grp].items():
            validate(rec, EVAL, f"manifest.{grp}[{t}]")
            if rec["selection_status"] != want: raise ValueError(f"manifest.{grp}[{t}]: selection_status must be {want}")
    if m["activation"]["status"] == "active" and not m["activation"]["act"]: raise ValueError("manifest.activation: active requires a named act")


def spec_binding(rec):
    c, want = rec["semantics"]["spec_commit"], rec["semantics"]["spec_sha256"]
    try:
        got = sha_b(subprocess.check_output(["git", "--no-optional-locks", "-C", ROOT, "show", f"{c}:{rec['semantics']['spec_path']}"]))
    except Exception as e:
        return {"verdict": "UNAVAILABLE", "error": repr(e)[:100]}
    return {"verdict": "BOUND" if got == want else "MISMATCH", "spec_commit": c, "expected": want, "actual": got}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="ski@v1"); ap.add_argument("--module", required=True); ap.add_argument("--wheel", default=None)
    ap.add_argument("--registry", default=DEF_REG); ap.add_argument("--manifest", default=DEF_MAN); ap.add_argument("--sigma-repo", default=None)
    a = ap.parse_args()
    out = {"schema": "wrt-007-evaluator-check-receipt/2", "reproducer_sha256": sha(os.path.abspath(__file__)), "tag": a.tag,
           "authority": "repository-default" if (os.path.abspath(a.registry) == DEF_REG and os.path.abspath(a.manifest) == DEF_MAN) else "caller-supplied",
           "registry_sha256": sha(a.registry), "manifest_sha256": sha(a.manifest), "bindings": {}, "axes": {}, "verdict": None, "credit_bearing": False}
    def refuse(v, **kw):
        out["verdict"] = v; out.update(kw); print(json.dumps(out, indent=1, sort_keys=True, default=str)); sys.exit(1)
    try:
        reg, man = json.load(open(a.registry)), json.load(open(a.manifest)); validate_registry(reg); validate_manifest(man)
    except Exception as e:
        refuse("REGISTRY_OR_MANIFEST_INVALID", error=str(e)[:240])
    out["bindings"]["manifest_registry_sha256"] = "BOUND" if man["registry_sha256"] == out["registry_sha256"] else "MISMATCH"
    if a.tag not in reg["tags"] or reg["tags"][a.tag]["status"] != "registered": refuse("TAG_NOT_REGISTERED")
    if a.tag in man["candidates"] and a.tag not in man["evaluators"]: refuse("EVALUATOR_IS_INERT_CANDIDATE")
    if a.tag not in man["evaluators"]: refuse("NO_ACTIVE_EVALUATOR_FOR_TAG")
    rec, sel = reg["tags"][a.tag], man["evaluators"][a.tag]
    out["selected_runtime_record_commitment"] = commit(rec); out["selected_manifest_record_commitment"] = commit(sel)
    out["bindings"]["selected_runtime_record"] = "BOUND" if sel["selected_runtime_record_commitment"] == commit(rec) else "MISMATCH"
    out["bindings"]["spec_bytes"] = spec_binding(rec)
    # specimen map: exact closed filename → digest, checked before anything runs
    spec_map = rec["vector_manifest"]["warrant_ski_specimen"]["files_sha256"]; skidir = os.path.join(ROOT, rec["vector_manifest"]["warrant_ski_specimen"]["path"])
    actual = {fn: sha(os.path.join(skidir, fn)) for fn in sorted(os.listdir(skidir))}
    out["bindings"]["ski_specimen_map"] = "BOUND" if actual == spec_map else {"verdict": "DRIFT", "missing": sorted(set(spec_map) - set(actual)), "extra": sorted(set(actual) - set(spec_map)),
                                                                                    "changed": sorted(k for k in set(spec_map) & set(actual) if spec_map[k] != actual[k])}
    bad = [k for k, v in out["bindings"].items() if (v != "BOUND" and not (isinstance(v, dict) and v.get("verdict") == "BOUND"))]
    if bad: refuse("BINDING_FAILURE", failed_bindings=bad)
    # module identity BEFORE import
    got = sha(a.module); out["axes"]["module_identity"] = {"candidate_sha256": got, "pinned_sha256": sel["module_sha256"], "verdict": "MATCH" if got == sel["module_sha256"] else "MISMATCH"}
    if a.wheel:
        try:
            wsha = sha(a.wheel)
            with zipfile.ZipFile(a.wheel) as z:
                names = [n for n in z.namelist() if n.endswith("sigma_glyph.py") and "/" not in n]
                inside = sha_b(z.read(names[0])) if names else None
            ok = wsha == sel["artifact"]["wheel_sha256"] and inside == sel["module_sha256"] == got
            out["axes"]["artifact_identity"] = {"wheel_sha256": wsha, "pinned_wheel_sha256": sel["artifact"]["wheel_sha256"], "module_in_wheel_sha256": inside, "verdict": "VERIFIED" if ok else "MISMATCH"}
        except Exception as e:
            out["axes"]["artifact_identity"] = {"verdict": "MISMATCH", "error": repr(e)[:120]}
    else:
        out["axes"]["artifact_identity"] = {"verdict": "NOT_VERIFIED", "note": "no --wheel given; only the module file was examined"}
    if out["axes"]["module_identity"]["verdict"] != "MATCH":
        out["axes"]["semantic_conformance"] = {"verdict": "NOT_RUN", "reason": "module not imported: sha256 does not match the active selection"}
        refuse("NOT_THE_PINNED_EVALUATOR")
    # semantic conformance against the tag's registry manifest
    cmd = ["python3", os.path.join(ROOT, "proposals", "wrt-006-model", "differential.py"), "--new", a.module] + (["--sigma-repo", a.sigma_repo] if a.sigma_repo else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    try: recpt = json.loads(r.stdout)
    except Exception: recpt = {"error": "no receipt", "stderr": r.stderr[-300:]}
    v, vm = recpt.get("verdicts", {}), rec["vector_manifest"]["sigma_book1_suite"]
    per, suites = recpt.get("axes", {}).get("E1_conformance", {}).get("per_suite", {}), recpt.get("suites", {})
    reg_suite = [k for k, d in suites.items() if isinstance(d, dict) and d.get("sha256") == vm["sha256"]]
    reg_ok = bool(reg_suite) and per.get(reg_suite[0], {}).get("verdict") == "PASS" and set(per[reg_suite[0]].get("required_fields") or []) >= set(vm["required_fields"])
    others_ok = all(x["verdict"] == "PASS" or (x["verdict"].startswith("PARTIAL_UNREPORTABLE:") and not (set(x["verdict"].split(":", 1)[1].split(",")) & set(vm["required_fields"])))
                    for k, x in per.items() if k not in reg_suite)
    receipt_bound = sel["conformance_receipt_sha256"] is not None and recpt.get("core_sha256") == sel["conformance_receipt_sha256"]
    sem_ok = v.get("suite_shape") == "MATCH" and reg_ok and others_ok and recpt.get("gate", {}).get("E0_ok") is True and v.get("differential_agreement") == "MATCH" and v.get("ski_specimen") == "MATCH"
    out["axes"]["semantic_conformance"] = {"verdict": "PASS" if sem_ok else "FAIL", "registry_binding": {"registry_suite_sha256": vm["sha256"], "matched_suite_document": reg_suite[0] if reg_suite else None, "required_fields": vm["required_fields"]},
                                           "registry_suite_pass": reg_ok, "other_suites_ok": others_ok, "wrt006_core_sha256": recpt.get("core_sha256"),
                                           "manifest_conformance_receipt_sha256": sel["conformance_receipt_sha256"], "receipt_bound": receipt_bound, "wrt006_receipt": recpt, "boundary_axis_gated": False}
    out["bindings"]["conformance_receipt"] = "BOUND" if receipt_bound else "MISMATCH"
    all_ok = sem_ok and receipt_bound
    out["activation"] = man["activation"]
    if out["authority"] != "repository-default":
        out["verdict"] = "TEST_PROFILE_RESULT"
    else:
        out["verdict"] = ("ARTIFACT_AND_MODULE_PINNED_AND_CONFORMING" if (all_ok and out["axes"]["artifact_identity"]["verdict"] == "VERIFIED") else "MODULE_PIN_MATCH_AND_CONFORMING" if all_ok else "PINNED_BUT_NOT_CONFORMING")
        # WRT-007 is CLOSED/DEFERRED (proposal §8): this reproducer is design evidence and is unconditionally
        # non-crediting. Activation (externally bound manifest/registry/release/authority) is a separate act;
        # a string in `activation.act` must never mint credit (third-gate P0).
        out["credit_bearing"] = False
        out["credit_note"] = "non-crediting by construction (WRT-007 §8); activation is a separate governance act"
    print(json.dumps(out, indent=1, sort_keys=True, default=str)); sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
