#!/usr/bin/env python3
"""Concrete refusal/mutation controls, plus offline reconstruction of frozen cases."""
import argparse
import copy
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import zipfile
from unittest.mock import patch

import audit as A
import evidence

HERE = Path(__file__).resolve().parent
passed = []


def check(label, condition):
    assert condition, label
    passed.append(label)
    print("PASS", label)


def refuses(label, code, fn):
    try:
        fn()
    except A.Refused as e:
        check(label, e.code == code)
    else:
        raise AssertionError(label + " unexpectedly admitted")


def synthetic_doc(doc, root_req, bridge_req, root_extras=(), bridge_extra=False):
    doc = copy.deepcopy(doc)
    entries, raw = [], {}
    for name, reqs in [("warrant-loops", root_req), ("audit-bridge", bridge_req), ("sigma-glyph", [])]:
        text = "Metadata-Version: 2.3\nName: " + name + "\nVersion: 1\n"
        if name == "warrant-loops" and root_extras:
            text += "".join("Provides-Extra: " + e + "\n" for e in root_extras)
        if name == "audit-bridge" and bridge_extra:
            text += "Provides-Extra: feature\n"
        text += "".join("Requires-Dist: " + req + "\n" for req in reqs) + "\n"
        data = text.encode()
        h = A.digest(data)
        raw[h] = data
        entries.append({"sha256": h, "name": name, "version": "1", "origin": {"kind": "synthetic"}})
    case = {"kind": "synthetic-control", "artifact_ids": [a["sha256"] for a in entries],
            "root": "warrant-loops", "extras": list(root_extras), "forbidden": ["sigma-glyph"], "required": []}
    doc["artifacts"] = entries
    return doc, case, raw


def main(cache):
    root = HERE / "fixture"
    manifest = root / "manifest.json"
    pin = (root / "manifest.sha256").read_text().strip()
    check("frozen manifest pin", A.digest(manifest.read_bytes()) == pin)
    doc = A.loads(manifest.read_bytes())
    baseline = A.verify(doc, root, cache)
    check("full wheel bytes verified, not Sigma execution", baseline["binding"] == "WHEEL_BYTES_VERIFIED" and baseline["sigma_execution"] == "NOT_RUN")
    check("real cases positive, transitive control negative", [c["reference"]["predicate"] for c in baseline["cases"]] == [True, True, False])
    check("explicit transitive witness", baseline["cases"][2]["reference"]["forbidden_paths"] == [["warrant-loops", "audit-bridge", "sigma-glyph"]])
    check("metadata-only has no wheel binding credit", A.verify(doc, root, cache, metadata_only=True)["binding"] == "METADATA_ONLY_UNVERIFIED")
    wrong = copy.deepcopy(doc); wrong["extra"] = True
    refuses("unknown manifest member", "SCHEMA", lambda: A.verify(wrong, root, cache))
    wrong = copy.deepcopy(doc); del wrong["target"]["marker_environment"]["sys_platform"]
    refuses("missing marker value cannot default to host", "SCHEMA", lambda: A.verify(wrong, root, cache))
    wrong = copy.deepcopy(doc); wrong["cases"][0]["graph"]["evaluation"]["edges"] = []
    refuses("forged graph with the same TRUE answer", "GRAPH_BINDING", lambda: A.verify(wrong, root, cache))
    wrong = copy.deepcopy(doc); wrong["cases"][0]["extras"] = ["missing-extra"]
    refuses("undeclared requested extra", "EXTRA", lambda: A.verify(wrong, root, cache))
    wrong = copy.deepcopy(doc); wrong["cases"][1]["artifact_ids"] = [h for h in wrong["cases"][1]["artifact_ids"]
        if next(a for a in wrong["artifacts"] if a["sha256"] == h)["name"] != "sigma-glyph"]
    refuses("missing active dependency", "MISSING_DEPENDENCY", lambda: A.verify(wrong, root, cache))
    wrong = copy.deepcopy(doc); wrong["cases"][0]["artifact_ids"] = list(wrong["cases"][1]["artifact_ids"])
    refuses("orphan selected inventory", "ORPHAN_INVENTORY", lambda: A.verify(wrong, root, cache))
    wrong = copy.deepcopy(doc); next(a for a in wrong["artifacts"] if a["origin"]["kind"] == "pypi")["origin"]["url"] = "https://example.org/arbitrary.whl"
    refuses("arbitrary artifact endpoint", "ORIGIN", lambda: A.verify(wrong, root, cache))
    wrong = copy.deepcopy(doc); first = next(iter(wrong["source"]["package_files"])); wrong["source"]["package_files"][first] = "00" * 32
    refuses("candidate/source package map mismatch", "SOURCE", lambda: A.verify(wrong, root, cache))
    refuses("duplicate METADATA Name", "METADATA", lambda: A.metadata(b"Name: a\nName: b\nVersion: 1\n\n"))
    refuses("direct URLs are outside bounded profile", "DIRECT_URL", lambda: A.metadata(b"Name: a\nVersion: 1\nRequires-Dist: b @ https://example.org/b.whl\n\n"))
    sdoc, case, raw = synthetic_doc(doc, ["audit-bridge[feature]"], ['sigma-glyph; extra == "feature"'], bridge_extra=True)
    g = A.reconstruct(sdoc, case, raw)
    check("dependency extras propagate transitively", A.reference(g)["predicate"] is False)
    sdoc, case, raw = synthetic_doc(doc, ["audit-bridge"], ["warrant-loops", "sigma-glyph"])
    check("cycles terminate with correct reachability", A.reference(A.reconstruct(sdoc, case, raw))["predicate"] is False)
    sdoc, case, raw = synthetic_doc(doc, ['audit-bridge; python_version >= "3.12"'], ["sigma-glyph"])
    check("explicit target activates marker", A.reference(A.reconstruct(sdoc, case, raw))["predicate"] is False)
    sdoc["target"]["marker_environment"]["python_version"] = "3.11"
    sdoc["target"]["marker_environment"]["python_full_version"] = "3.11.17"
    refuses("changed target is not silently interpreted as host", "ORPHAN_INVENTORY", lambda: A.reconstruct(sdoc, case, raw))
    sdoc, case, raw = synthetic_doc(doc, ["audit-bridge>=2"], ["sigma-glyph"])
    refuses("selected version violates requirement", "VERSION", lambda: A.reconstruct(sdoc, case, raw))
    sdoc, case, raw = synthetic_doc(doc, ["audit-bridge", "audit-bridge", "audit-bridge"], ["sigma-glyph"])
    graph = A.reconstruct(sdoc, case, raw)
    check("duplicate requirements become unique edges", len(graph["evaluation"]["edges"]) == 2)
    reordered = copy.deepcopy(doc)
    reordered["artifacts"].reverse()
    for c in reordered["cases"]: c["artifact_ids"].reverse()
    check("inventory ordering does not change graph", [c["graph_sha256"] for c in A.verify(reordered, root, cache)["cases"]] == [c["graph_sha256"] for c in baseline["cases"]])
    with tempfile.TemporaryDirectory(prefix="dependency-audit-test-") as tmp:
        tmp = Path(tmp)
        alias = tmp / "operator-cache-alias"
        alias.symlink_to(cache, target_is_directory=True)
        check("operator cache root resolves host aliases", A.verify(doc, root, alias)["binding"] == "WHEEL_BYTES_VERIFIED")
        wrong_json = tmp / "wrong.json"
        wrong_json.write_text('{"a":1,"a":2}')
        refuses("duplicate JSON keys", "JSON", lambda: A.loads(wrong_json.read_bytes()))
        wrong_json.write_text('{"a":1.0}')
        refuses("JSON floats", "JSON", lambda: A.loads(wrong_json.read_bytes()))
        a = next(a for a in doc["artifacts"] if a["origin"]["kind"] == "candidate")
        original = A.artifact_path(root, cache, a)
        changed = tmp / a["filename"]
        changed.write_bytes(original.read_bytes() + b"changed")
        refuses("changed wheel bytes", "WHEEL_DIGEST", lambda: A.read_wheel(changed, a))
        refuses("missing wheel bytes", "MISSING_WHEEL", lambda: A.read_wheel(tmp / "absent.whl", a))
        sigma = next(a for a in doc["artifacts"] if a["name"] == "sigma-glyph")
        data = io.BytesIO()
        with zipfile.ZipFile(A.artifact_path(root, cache, sigma)) as src, zipfile.ZipFile(data, "w") as dst:
            for member in src.infolist():
                body = src.read(member)
                dst.writestr(member, body + b"\n" if member.filename == "sigma_provider.py" else body)
        altered_wheel = data.getvalue()
        new_id = A.digest(altered_wheel)
        changed_doc = copy.deepcopy(doc)
        for item in changed_doc["artifacts"]:
            if item["sha256"] == sigma["sha256"]:
                item.update(sha256=new_id, size=len(altered_wheel))
        for c in changed_doc["cases"]:
            c["artifact_ids"] = [new_id if h == sigma["sha256"] else h for h in c["artifact_ids"]]
        new_cache = tmp / "wheel-cache"
        shutil.copytree(cache, new_cache)
        dst = new_cache / new_id / sigma["filename"]
        dst.parent.mkdir()
        dst.write_bytes(altered_wheel)
        refuses("same-version rehashed provider substitution", "PROVIDER", lambda: A.verify(changed_doc, root, new_cache))
        p = subprocess.run([sys.executable, str(HERE / "audit.py"), "fetch", "--manifest", str(manifest),
                            "--manifest-sha256", "00" * 32, "--wheelhouse", str(tmp / "no-network")],
                           capture_output=True, text=True)
        check("bad operator pin refuses before cache/network", p.returncode == 2 and 'MANIFEST_PIN' in p.stdout and not (tmp / "no-network").exists())
        ev = evidence.prepare(manifest, pin, "base", cache)
        check("input evidence gives no computation/acceptance credit", ev["state"] == "INPUT_VERIFIED_ENCODING_PENDING" and ev["warrant_acceptance"] == "NOT_RUN")
        changed_doc = copy.deepcopy(doc)
        changed_doc["target"]["marker_environment"]["platform_release"] += "-other-observation"
        other = root / "test-other-manifest.json"
        # Keep the original fixture untouched; use a sibling manifest transiently.
        try:
            other.write_bytes(A.canon(changed_doc))
            other_pin = A.digest(other.read_bytes())
            other_ev = evidence.prepare(other, other_pin, "base", cache)
            check("same computed answer, different target binding", ev["reference_only"] == other_ev["reference_only"] and ev["binding_id"] != other_ev["binding_id"])
            refuses("old pin cannot authorize another observation", "MANIFEST_PIN", lambda: evidence.prepare(other, pin, "base", cache))
            pinned_bytes = manifest.read_bytes()
            other.write_bytes(pinned_bytes)
            read_original = A.read_bounded

            def replace_after_read(path, *args):
                raw = read_original(path, *args)
                if path == other:
                    other.write_bytes(A.canon(changed_doc))
                return raw

            with patch.object(A, "read_bounded", side_effect=replace_after_read):
                snapshot_ev = evidence.prepare(other, pin, "base", cache)
            check("manifest replacement cannot change the pinned snapshot",
                  snapshot_ev["binding_id"] == ev["binding_id"])
        finally:
            other.unlink(missing_ok=True)
    print(f"DEPENDENCY-AUDIT: {len(passed)} controls PASS; Sigma execution/term binding and application acceptance NOT_RUN")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wheelhouse", type=Path, required=True)
    main(p.parse_args().wheelhouse.resolve())
