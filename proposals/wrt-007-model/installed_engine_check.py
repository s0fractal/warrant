#!/usr/bin/env python3
"""WRT-007 reproducer (rev 2): does a candidate evaluator match what a Warrant release selected for a tag,
and does it conform to the tag's normative vector manifest?

Three separately reported axes:
  artifact_identity     VERIFIED | NOT_VERIFIED | MISMATCH   (only if --wheel is given: wheel sha and the module inside it)
  module_identity       MATCH | MISMATCH                       (sha256 of the candidate file vs the release manifest's pin — computed BEFORE any import)
  semantic_conformance  PASS | FAIL | NOT_RUN                  (WRT-006 differential with the candidate as E1; full receipt embedded)

Refusal order: a module whose sha256 does not match the pin is NEVER imported or executed —
the differential is not run, and the verdict is NOT_THE_PINNED_EVALUATOR. Registry and manifest are
closed-schema; their digests and the selected records' commitments are in the receipt. A registry or
manifest supplied by the caller (--registry/--manifest differing from the repository defaults) marks the
run `authority: caller-supplied` and the verdict TEST_PROFILE_RESULT — never credit-bearing.
Writes nothing.
"""
import argparse, hashlib, json, os, subprocess, sys, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
DEF_REG, DEF_MAN = os.path.join(HERE, "runtime-registry.json"), os.path.join(HERE, "release-evaluator-manifest.json")
HEX64 = lambda x: isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def commit(obj): return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def closed(obj, keys, where):
    extra, missing = set(obj) - set(keys), set(keys) - set(obj)
    if extra or missing:
        raise ValueError(f"{where}: closed schema violated (extra={sorted(extra)}, missing={sorted(missing)})")


def validate_registry(r):
    closed(r, ("schema", "note", "tags"), "registry")
    if r["schema"] != "warrant/runtime-registry@draft-0": raise ValueError("registry: unknown schema")
    for t, rec in r["tags"].items():
        closed(rec, ("status", "semantics", "body_versions", "vector_manifest", "store_contract"), f"registry[{t}]")


def validate_manifest(m):
    closed(m, ("schema", "note", "warrant_release", "registry_ref", "evaluators"), "manifest")
    if m["schema"] != "warrant/release-evaluator-manifest@draft-0": raise ValueError("manifest: unknown schema")
    for t, rec in m["evaluators"].items():
        closed(rec, ("form", "module", "module_sha256", "artifact", "conformance_receipt_sha256", "conformance_note"), f"manifest[{t}]")
        if not HEX64(rec["module_sha256"]): raise ValueError(f"manifest[{t}]: module_sha256 must be hex64")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="ski@v1"); ap.add_argument("--module", required=True)
    ap.add_argument("--wheel", default=None, help="optional: the distribution wheel the module is claimed to come from")
    ap.add_argument("--registry", default=DEF_REG); ap.add_argument("--manifest", default=DEF_MAN); ap.add_argument("--sigma-repo", default=None)
    a = ap.parse_args()
    out = {"schema": "wrt-007-evaluator-check-receipt/1", "reproducer_sha256": sha(os.path.abspath(__file__)), "tag": a.tag,
           "authority": "repository-default" if (os.path.abspath(a.registry) == DEF_REG and os.path.abspath(a.manifest) == DEF_MAN) else "caller-supplied",
           "registry_sha256": sha(a.registry), "manifest_sha256": sha(a.manifest), "axes": {}, "verdict": None}
    try:
        reg, man = json.load(open(a.registry)), json.load(open(a.manifest))
        validate_registry(reg); validate_manifest(man)
    except Exception as e:
        out["verdict"] = "REGISTRY_OR_MANIFEST_INVALID"; out["error"] = str(e)[:200]; print(json.dumps(out, indent=1)); sys.exit(1)
    if a.tag not in reg["tags"] or reg["tags"][a.tag]["status"] != "registered":
        out["verdict"] = "TAG_NOT_REGISTERED"; print(json.dumps(out, indent=1)); sys.exit(1)
    if a.tag not in man["evaluators"]:
        out["verdict"] = "NO_EVALUATOR_SELECTED_FOR_TAG"; print(json.dumps(out, indent=1)); sys.exit(1)
    sel = man["evaluators"][a.tag]
    out["selected_registry_record_commitment"] = commit(reg["tags"][a.tag]); out["selected_manifest_record_commitment"] = commit(sel)

    # --- module identity, BEFORE any import
    got = sha(a.module); out["axes"]["module_identity"] = {"candidate_sha256": got, "pinned_sha256": sel["module_sha256"], "verdict": "MATCH" if got == sel["module_sha256"] else "MISMATCH"}
    # --- artifact identity (optional)
    if a.wheel:
        try:
            wsha = sha(a.wheel); inside = None
            with zipfile.ZipFile(a.wheel) as z:
                names = [n for n in z.namelist() if n.endswith("sigma_glyph.py") and "/" not in n]
                inside = hashlib.sha256(z.read(names[0])).hexdigest() if names else None
            ok = wsha == sel["artifact"].get("wheel_sha256") and inside == sel["module_sha256"] == got
            out["axes"]["artifact_identity"] = {"wheel_sha256": wsha, "pinned_wheel_sha256": sel["artifact"].get("wheel_sha256"), "module_in_wheel_sha256": inside, "verdict": "VERIFIED" if ok else "MISMATCH"}
        except Exception as e:
            out["axes"]["artifact_identity"] = {"verdict": "MISMATCH", "error": repr(e)[:120]}
    else:
        out["axes"]["artifact_identity"] = {"verdict": "NOT_VERIFIED", "note": "no --wheel given; only the module file was examined"}
    if out["axes"]["module_identity"]["verdict"] != "MATCH":
        out["axes"]["semantic_conformance"] = {"verdict": "NOT_RUN", "reason": "module not imported: sha256 does not match the release manifest pin"}
        out["verdict"] = "NOT_THE_PINNED_EVALUATOR"; print(json.dumps(out, indent=1, sort_keys=True)); sys.exit(1)

    # --- semantic conformance: WRT-006 differential with the candidate as E1; full receipt embedded and digested
    cmd = ["python3", os.path.join(ROOT, "proposals", "wrt-006-model", "differential.py"), "--new", a.module] + (["--sigma-repo", a.sigma_repo] if a.sigma_repo else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        rec = json.loads(r.stdout)
    except Exception:
        rec = {"error": "no receipt", "stderr": r.stderr[-300:]}
    v = rec.get("verdicts", {})
    # Semantic conformance is judged against the TAG's registry vector manifest, not against whatever suites
    # the differential happened to load: the suite whose sha256 the registry names must be PASS under the
    # registry's required fields; any other suite may be PARTIAL_UNREPORTABLE only on fields the registry does
    # not require. Agreement with the historical ski@v1 engine (E0) and the shipped specimen are required too.
    vm = reg["tags"][a.tag]["vector_manifest"]["sigma_book1_suite"]
    per = rec.get("axes", {}).get("E1_conformance", {}).get("per_suite", {})
    suites = rec.get("suites", {})
    reg_suite = [k for k, d in suites.items() if isinstance(d, dict) and d.get("sha256") == vm["sha256"]]
    binding = {"registry_suite_sha256": vm["sha256"], "matched_suite_document": reg_suite[0] if reg_suite else None,
               "required_fields": vm["required_fields"]}
    reg_ok = bool(reg_suite) and per.get(reg_suite[0], {}).get("verdict") == "PASS" \
        and set(per[reg_suite[0]].get("required_fields") or []) >= set(vm["required_fields"])
    others_ok = all(
        r["verdict"] == "PASS" or (r["verdict"].startswith("PARTIAL_UNREPORTABLE:")
                                   and not (set(r["verdict"].split(":", 1)[1].split(",")) & set(vm["required_fields"])))
        for k, r in per.items() if k not in reg_suite)
    sem_ok = (v.get("suite_shape") == "MATCH" and reg_ok and others_ok and rec.get("gate", {}).get("E0_ok") is True
              and v.get("differential_agreement") == "MATCH" and v.get("ski_specimen") == "MATCH")
    out["axes"]["semantic_conformance"] = {"verdict": "PASS" if sem_ok else "FAIL", "registry_binding": binding,
                                           "registry_suite_pass": reg_ok, "other_suites_ok": others_ok,
                                           "wrt006_receipt_sha256": hashlib.sha256(r.stdout.encode()).hexdigest(),
                                           "wrt006_receipt": rec, "boundary_axis_gated": False}
    all_ok = sem_ok
    if out["authority"] != "repository-default":
        out["verdict"] = "TEST_PROFILE_RESULT"; out["credit_bearing"] = False
    else:
        out["credit_bearing"] = all_ok
        out["verdict"] = ("ARTIFACT_AND_MODULE_PINNED_AND_CONFORMING" if (all_ok and out["axes"]["artifact_identity"]["verdict"] == "VERIFIED")
                          else "MODULE_PIN_MATCH_AND_CONFORMING" if all_ok else "PINNED_BUT_NOT_CONFORMING")
    print(json.dumps(out, indent=1, sort_keys=True, default=str)); sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
