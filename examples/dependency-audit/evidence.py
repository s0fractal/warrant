#!/usr/bin/env python3
"""Prepare application input evidence for #151; no computation/acceptance credit."""
import argparse
import json
from pathlib import Path
import sys

import audit as A


def prepare(manifest, operator_pin, case_id, wheelhouse):
    raw = A.read_bounded(manifest, 1024 * 1024)
    A.need(A.digest(raw) == operator_pin, "MANIFEST_PIN", "operator's exact instance")
    doc = A.loads(raw)
    A.need(A.canon(doc) == raw, "JSON", "canonical instance")
    verified = A.verify(doc, manifest.parent.resolve(), wheelhouse.resolve())
    cases = [c for c in doc["cases"] if c["id"] == case_id]
    A.need(len(cases) == 1, "CASE", "unknown case")
    c = cases[0]
    binding = {"manifest_sha256": operator_pin, "case": case_id, "case_kind": c["kind"],
               "source_commit": doc["source"]["commit"],
               "target_sha256": A.digest(A.canon(doc["target"])),
               "contract_sha256": doc["contract_sha256"], "audit_sha256": doc["tools"]["audit_sha256"],
               "artifact_ids": sorted(c["artifact_ids"]), "graph_sha256": c["graph_sha256"],
               "evaluation_sha256": A.digest(A.canon(c["graph"]["evaluation"]))}
    return {"schema": "warrant-dependency-input-evidence/1", "state": "INPUT_VERIFIED_ENCODING_PENDING",
            "binding_id": A.digest(A.canon(binding)), "binding": binding, "graph": c["graph"],
            "artifact_binding": verified["binding"], "source_correspondence": "COLLECTOR_OBSERVATION",
            "reference_only": c["reference"], "sigma_execution": "NOT_RUN", "warrant_acceptance": "NOT_RUN",
            "expected_provider": A.PROVIDER, "source_completeness": "UNATTESTED"}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--manifest-sha256", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--wheelhouse", type=Path, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(prepare(a.manifest, a.manifest_sha256, a.case, a.wheelhouse), sort_keys=True, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as e:
        print(json.dumps({"state": "REFUSED", "code": getattr(e, "code", "MALFORMED"), "detail": str(e)}))
        sys.exit(2)
